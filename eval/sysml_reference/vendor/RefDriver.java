import org.omg.sysml.interactive.SysMLInteractive;
import org.omg.sysml.interactive.SysMLInteractiveResult;
import org.eclipse.xtext.validation.Issue;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

/**
 * Minimal standalone driver around the OMG SysML v2 Pilot Implementation's
 * "SysML Interactive" API (the same class the Jupyter kernel uses under the
 * hood). Reads SysML/KerML source text from a file, parses + validates it
 * against the standard library, and prints the result as a single line of
 * JSON to stdout.
 *
 * Usage:
 *   java -cp <fatjar> RefDriver <libraryDir> <sourceFile> [encoding]
 *
 * Output JSON shape:
 *   {"crashed": bool, "success": bool, "issues": [
 *       {"severity": str, "line": int|null, "column": int|null,
 *        "message": str, "syntaxError": bool}
 *   ], "exception": str|null}
 */
public class RefDriver {

    public static void main(String[] args) {
        PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        if (args.length < 2) {
            out.println("{\"crashed\": true, \"success\": false, \"issues\": [], "
                    + "\"exception\": \"Usage: RefDriver <libraryDir> <sourceFile>\"}");
            System.exit(2);
            return;
        }
        String libraryPath = args[0];
        String sourceFile = args[1];

        StringBuilder sb = new StringBuilder();
        try {
            String text = new String(Files.readAllBytes(Paths.get(sourceFile)), StandardCharsets.UTF_8);

            SysMLInteractive si = SysMLInteractive.getInstance();
            si.setVerbose(false);
            si.loadLibrary(libraryPath);

            SysMLInteractiveResult result = si.process(text, false);

            sb.append("{");
            if (result.getException() != null) {
                sb.append("\"crashed\": true, \"success\": false, \"issues\": [], \"exception\": ")
                  .append(jsonStr(String.valueOf(result.getException())))
                  .append("}");
                out.println(sb);
                return;
            }

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
            out.println(sb);
        } catch (Throwable t) {
            StringBuilder err = new StringBuilder();
            err.append(t).append("\n");
            for (StackTraceElement el : t.getStackTrace()) {
                err.append("\tat ").append(el).append("\n");
            }
            out.println("{\"crashed\": true, \"success\": false, \"issues\": [], \"exception\": "
                    + jsonStr(err.toString()) + "}");
        }
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
