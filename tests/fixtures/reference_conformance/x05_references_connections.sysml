package P {
	port def Pt;
	part def Sys {
		port a : Pt;
		port b : Pt;
		part c;
		part d;
		part e { out item x; }
		part f { in item x; }
		interface i0 connect a to b;
		interface i1 ::> i0 connect a to b;
		connection n0 connect c to d;
		connection n1 ::> n0 connect c to d;
		allocation l0 allocate c to d;
		allocation l1 ::> l0 allocate c to d;
		flow w0 from e.x to f.x;
		flow w1 ::> w0 from e.x to f.x;
	}
}
