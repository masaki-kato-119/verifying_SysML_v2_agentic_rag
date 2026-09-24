item def Tick;
state def L { entry; then A; state A; state B; transition first A then B { accept t : Tick; } }
