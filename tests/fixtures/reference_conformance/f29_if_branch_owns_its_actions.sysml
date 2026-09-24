item def C;
action def M { in c : ScalarValues::Boolean; action e { out x : C; } if c { action a { in y : C; out z : C; } action b { in y : C; } flow a.z to b.y; } }
