item def C;
action def M { in c : ScalarValues::Boolean; if c { action a { out z : C; } } else { action b { in y : C; } flow a.z to b.y; } }
