private import ScalarValues::*;
action def M { in c : Boolean; action a; action b; if c { perform a; then perform b; } }
