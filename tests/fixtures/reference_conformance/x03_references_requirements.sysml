package P {
	part def Person;
	part p : Person;
	requirement def R;
	requirement r0;
	requirement def RS {
		subject s ::> p;
	}
	concern def C {
		subject s;
		stakeholder sh ::> p;
	}
	case def K {
		objective o ::> r0;
	}
	verification def V {
		objective {
			verify requirement r1 ::> r0;
		}
	}
	part def Sys {
		requirement q0 : R;
		requirement q1 ::> q0;
		requirement q2 : R ::> q0;
		concern c0;
		concern c1 ::> c0;
		constraint k0;
		constraint k1 ::> k0;
		assert constraint k2 ::> k0;
		calc m0;
		calc m1 ::> m0;
	}
}
