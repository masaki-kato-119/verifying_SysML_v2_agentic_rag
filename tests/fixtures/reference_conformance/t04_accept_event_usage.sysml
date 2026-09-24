package P { occurrence def O; event occurrence tick : O;
state def L { entry; then A; state A; state B; transition first A accept tick then B; } }
