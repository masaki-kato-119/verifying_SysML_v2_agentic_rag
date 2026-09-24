item def C;
action def Base { in x : C; }
action def D :> Base { action b { in y : C; } flow x to b.y; }
