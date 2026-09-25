package P {
	individual part def Thing;
	enum def Color { red; green; }
	part def TGSDef;
	part def Sys {
		part TGS : TGSDef[2];
		part tgs1 ::> TGS[0];
		part tgs2 references TGS;
		item x0;
		item x1 ::> x0;
		item x2 references x0;
		attribute a0;
		attribute a1 references a0;
		f0;
		f1 references f0;
		occurrence o0;
		occurrence o1 ::> o0;
		event occurrence e1 ::> o0;
		individual t0 : Thing;
		individual t1 ::> t0;
		enum c0 : Color;
		enum c1 : Color ::> c0;
	}
}
