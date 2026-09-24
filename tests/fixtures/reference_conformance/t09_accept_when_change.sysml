private import ScalarValues::*;
state def L { attribute x : Integer; entry; then A; state A; state B; transition first A accept when x > 0 then B; }
