part def D; part d : D;
requirement def R { subject s : D; }
requirement r : R { subject = d; }
satisfy requirement r by d;
