part def D;
requirement def R { subject s : D; }
part d : D { satisfy r; }
requirement r : R { subject = d; }
