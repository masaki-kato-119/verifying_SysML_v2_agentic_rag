part def D; part d : D;
requirement def R { subject s : D; }
requirement r : R { subject :>> s = d; }
satisfy r by d;
