item def C;
action def A { out x : C; }
action def B { action a : A { out :>> x; } action b { in y : C; } flow a.x to b.y; }
