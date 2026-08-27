package TestPackage {
    part def Vehicle {
        attribute mass : Real;
        attribute speed : Real;
        
        port fuelPort : FuelPort;
        port enginePort : EnginePort;
    }
    
    part def Engine {
        attribute power : Real;
        attribute efficiency : Real;
        
        port intake : IntakePort;
        port exhaust : ExhaustPort;
    }
    
    part testVehicle : Vehicle {
        part engine : Engine;
        
        connect fuelPort to engine.intake;
        connect enginePort to engine.exhaust;
    }
    
    interface def FuelPort;
    interface def EnginePort;
    interface def IntakePort;
    interface def ExhaustPort;
}