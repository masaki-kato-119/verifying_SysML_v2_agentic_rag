item def C;
action def B { action a { out x : C; } action b { in y : C; } flow a.nope to b.y; }
