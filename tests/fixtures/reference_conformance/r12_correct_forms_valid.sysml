private import ScalarValues::*;
private import ISQ::*;
private import SI::*;
item def Coffee;
part def Vehicle {
    attribute mass : MassValue = 1.8 [kg];
    attribute enabled : Boolean;
}
action def Brew {
    action extract { out coffee : Coffee; }
    action serve { in coffee : Coffee; }
    flow extract.coffee to serve.coffee;
}
constraint def WithinLimit {
    in speed : Real;
    in limit : Real;
    speed <= limit
}
