item def Coffee;
action def Brew {
    action extract { out coffee : Coffee; }
    action finish {
        action addSugar { in coffeeIn : Coffee; }
    }
    flow extract.coffee to addSugar.coffeeIn;
}
