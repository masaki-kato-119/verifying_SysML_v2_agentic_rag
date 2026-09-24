item def C;
action a { out x : C; }
action b { in y : C; }
flow a.x to b.y;
