item def C;
action def B { action a { out x : C; } action b { in y : C; } flow f of C from q.x to b.y; }
