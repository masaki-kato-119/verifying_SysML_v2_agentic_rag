item def C;
action def A { out x : C; }
action def B { action a : A; action b { in y : C; } flow a.nope to b.y; }
