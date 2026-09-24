state def Light {
    entry; then Red;
    state Red;
    state Green;
    transition first Red accept TimerEvent then Green;
}
