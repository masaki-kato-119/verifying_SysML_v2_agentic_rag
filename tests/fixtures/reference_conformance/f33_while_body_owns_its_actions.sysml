item def C;
action def M { in c : ScalarValues::Boolean; while c { action a { out z : C; } action b { in y : C; } flow a.z to b.y; } }
