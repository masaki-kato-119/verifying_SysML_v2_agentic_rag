import org.omg.sysml.interactive.SysMLInteractive;
import org.omg.sysml.interactive.SysMLInteractiveResult;
import org.eclipse.xtext.validation.Issue;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

/**
 * Minimal standalone driver around the OMG SysML v2 Pilot Implementation's
 * "SysML Interactive" API (the same class the Jupyter kernel uses under the
 * hood). Parses + validates SysML/KerML source against the standard library and
 * prints the result as a single line of JSON to stdout.
 *
 * Usage:
 *   java -cp &lt;fatjar&gt; RefDriver &lt;libraryDir&gt; &lt;sourceFile&gt;
 *   java -cp &lt;fatjar&gt; RefDriver &lt;libraryDir&gt; --batch     (paths on stdin)
 *
 * Output JSON shape:
 *   {"crashed": bool, "success": bool, "issues": [
 *       {"severity": str, "line": int|null, "column": int|null,
 *        "message": str, "syntaxError": bool}
 *   ], "exception": str|null}
 *
 * Batch mode exists because single-file mode pays for a JVM start and a full
 * si.loadLibrary() on every sample -- about 13 seconds each, which turns a
 * 730-sample run into more than two hours. In batch mode the library loads once
 * and paths are read from stdin, one per line, each answered with one result
 * line.
 *
 * Two details matter for correctness:
 *
 *  - Every batch result line is prefixed with RESULT_PREFIX. SysMLInteractive
 *    and the libraries under it can write to stdout on their own, and the
 *    caller needs a strict one-request-one-response correspondence rather than
 *    "the last line that looks like JSON".
 *  - si.removeResource() is called after each file. SysMLInteractive is the
 *    Jupyter kernel's interactive-session API: consecutive process() calls are
 *    cells of one session, so without dropping the previous resource, names
 *    declared by an earlier file could resolve from a later one -- silently
 *    making cross-file references resolve that should not. Whether that is
 *    enough is not assumed: batch results are compared against a serial run
 *    over all 730 samples before this mode is used for anything.
 */
public class RefDriver {

    /** Marks a result line so the caller can ignore anything else on stdout. */
    public static final String RESULT_PREFIX = "@@REFDRIVER@@";

    public static void main(String[] args) {
        PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        if (args.length < 2) {
            out.println(crashJson("Usage: RefDriver <libraryDir> (<sourceFile> | --batch)"));
            System.exit(2);
            return;
        }
        String libraryPath = args[0];
        boolean batch = "--batch".equals(args[1]);

        SysMLInteractive si;
        try {
            si = SysMLInteractive.getInstance();
            si.setVerbose(false);
            si.loadLibrary(libraryPath);
        } catch (Throwable t) {
            // In batch mode the caller cannot tell which request this belongs
            // to, so fail loudly with a non-zero exit instead of answering.
            out.println((batch ? RESULT_PREFIX : "") + crashJson(stackTrace(t)));
            System.exit(3);
            return;
        }

        if (!batch) {
            out.println(processOne(si, args[1]));
            return;
        }

        try (BufferedReader in = new BufferedReader(
                new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = in.readLine()) != null) {
                String path = line.trim();
                if (path.isEmpty()) {
                    continue;
                }
                out.println(RESULT_PREFIX + processOne(si, path));
            }
        } catch (Throwable t) {
            out.println(RESULT_PREFIX + crashJson(stackTrace(t)));
            System.exit(4);
        }
    }

    /**
     * Parse + validate one file and return its JSON result. Never throws: a
     * failure on one file must not end a batch run.
     */
    private static String processOne(SysMLInteractive si, String sourceFile) {
        try {
            String text = new String(Files.readAllBytes(Paths.get(sourceFile)), StandardCharsets.UTF_8);
            SysMLInteractiveResult result = si.process(text, false);

            if (result.getException() != null) {
                return crashJson(String.valueOf(result.getException()));
            }

            StringBuilder sb = new StringBuilder("{");
            List<Issue> issues = result.getIssues();
            sb.append("\"crashed\": false, ");
            sb.append("\"success\": ").append(!result.hasErrors()).append(", ");
            sb.append("\"issues\": [");
            for (int i = 0; i < issues.size(); i++) {
                Issue iss = issues.get(i);
                if (i > 0) sb.append(",");
                sb.append("{");
                sb.append("\"severity\": ").append(jsonStr(String.valueOf(iss.getSeverity()))).append(",");
                sb.append("\"line\": ").append(iss.getLineNumber() == null ? "null" : iss.getLineNumber()).append(",");
                sb.append("\"column\": ").append(iss.getColumn() == null ? "null" : iss.getColumn()).append(",");
                sb.append("\"syntaxError\": ").append(iss.isSyntaxError()).append(",");
                sb.append("\"message\": ").append(jsonStr(iss.getMessage()));
                sb.append("}");
            }
            sb.append("], \"exception\": null}");
            return sb.toString();
        } catch (Throwable t) {
            return crashJson(stackTrace(t));
        } finally {
            // Drop this file's resource so the next one does not see its
            // declarations. See the class comment for why this matters.
            try {
                si.removeResource();
            } catch (Throwable ignored) {
                // Nothing useful to do here; the comparison against the serial
                // run is what decides whether batch mode is usable at all.
            }
        }
    }

    private static String crashJson(String message) {
        return "{\"crashed\": true, \"success\": false, \"issues\": [], \"exception\": "
                + jsonStr(message) + "}";
    }

    private static String stackTrace(Throwable t) {
        StringBuilder err = new StringBuilder();
        err.append(t).append("\n");
        for (StackTraceElement el : t.getStackTrace()) {
            err.append("\tat ").append(el).append("\n");
        }
        return err.toString();
    }

    private static String jsonStr(String s) {
        if (s == null) return "null";
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append("\"");
        return sb.toString();
    }
}
