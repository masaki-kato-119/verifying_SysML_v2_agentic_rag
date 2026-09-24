item def Coffee;
action def Brew {
    action extract { out coffee : Coffee; }
    action serve { in coffee : Coffee; }
    flow coffee to serve.coffee;
}
