part def D; part d : D; part e : D;
requirement def R { subject s : D; }
requirement r : R { subject = d; }
satisfy r by e;
