port def P;
part def S { part p1 { port o : P; } part p2 { port i : P; } flow o to p2.i; }
