private import ScalarValues::*;
state def L { entry; then A; state A; state B; transition first A accept Boolean then B; }
