item def C;
part def Q { port o : ~P; }
port def P { in item c : C; }
part def S { part q : Q; part r { port i : P; } flow q.o.c to r.i.c; }
