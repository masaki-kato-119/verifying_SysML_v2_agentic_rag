state def S {
    state def Off;
    state def On {
        entry action setupSystem;
        do action performOperation;
        exit action cleanup;
    }

    transition first Off accept TurnOn if x > 0 do action logStart then On;
    transition OnToOff first On accept TurnOff then Off;
}
