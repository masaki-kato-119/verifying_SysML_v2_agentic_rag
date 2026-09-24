private import SI::*;
state def L { entry; then A; state A; state B; transition first A accept after 5 [s] then B; }
