constraint def WithinLimit {
    in speed : ScalarValues::Real;
    in limit : ScalarValues::Real;
    speed <= limit;
}
