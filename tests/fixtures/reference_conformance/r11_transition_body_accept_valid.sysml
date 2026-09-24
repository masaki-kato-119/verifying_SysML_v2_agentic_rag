item def Tick;
state def Light {
    entry; then Red;
    state Red;
    state Green;
    transition first Red then Green {
        accept t : Tick;
    }
}
