package P {
	part def Person;
	part p : Person;
	use case def U {
		subject s;
		actor ac ::> p;
		use case u0;
		include use case u1 ::> u0;
	}
	part def Sys {
		case c0;
		case c1 ::> c0;
		analysis a0;
		analysis a1 ::> a0;
		verification v0;
		verification v1 ::> v0;
		use case w0;
		use case w1 ::> w0;
		view vw0;
		view vw1 ::> vw0;
		viewpoint vp0;
		viewpoint vp1 ::> vp0;
		rendering r0;
		rendering r1 ::> r0;
	}
}
