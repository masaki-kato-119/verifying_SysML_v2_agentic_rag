private import Actions::*;
item def C;
action def B { action a : Action; action b { in y : C; } flow a.x to b.y; }
