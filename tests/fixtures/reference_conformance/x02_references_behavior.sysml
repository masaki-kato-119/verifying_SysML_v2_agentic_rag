package P {
	item x0;
	action a0;
	action def A {
		in item x1 ::> x0;
	}
	state def S {
		entry action e1 ::> a0;
		do action d1 ::> a0;
		exit action x2 ::> a0;
	}
	part def Sys {
		action b0;
		action b1 ::> b0;
		action b2 references b0;
		state s0;
		state s1 ::> s0;
		exhibit state s2 ::> s0;
	}
}
