port def P { out item c; }
interface def I { end p1 : P; end p2 : ~P; flow p1.c to p2.c; }
