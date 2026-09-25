package P {
	attribute def Oil;
	port def OilPort {
		port def OilIO {
			in oil : Oil;
		}
		port oilIn  : OilIO;
		port oilOut : ~OilIO;
	}
}
