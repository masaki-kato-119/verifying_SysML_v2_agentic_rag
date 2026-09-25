package P {
	port def ACPower;
	part def Charger {
		port acPowerPort : ACPower[2];
		port acPowerPortFw : ACPower ::> acPowerPort;
	}
}
