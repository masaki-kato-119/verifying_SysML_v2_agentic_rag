item def Tick; port def TP;
part def S { port p : TP; state s : L; }
state def L { entry; then A; state A; state B; transition first A accept Tick via p then B; }
