item def C;
action def Base { action a { out x : C; } }
action def D :> Base { action b { in y : C; } flow a.x to b.y; }
