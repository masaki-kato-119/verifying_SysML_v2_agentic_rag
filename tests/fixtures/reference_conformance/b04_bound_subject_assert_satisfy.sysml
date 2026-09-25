part def D; part d : D;
requirement def R { subject s : D; }
requirement r : R { subject = d; }
assert satisfy r by d;
