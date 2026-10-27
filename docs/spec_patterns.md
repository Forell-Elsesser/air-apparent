## Load patterns Spec
- Format: `W_<component>_<direction>`.
- Direction suffixes: `+X`, `-X`, `+Y`, `-Y`.
- W_Wall: Main-wall explicit pressures, including exposed stair pop-outs
- W_Parapet: Parapet pressures
- W_PH: Penthouse-body net loads applied to the windward faces
- W_Mech: Wind load on mechanical platform and components
- W_Ecc: Separate torsion patterns associated with each wind direction

## Load Patterns
1. W_Wall_+X
2. W_Wall_-X
3. W_Wall_+Y
4. W_Wall_-Y

5. W_Parapet_+X
6. W_Parapet_-X
7. W_Parapet_+Y
8. W_Parapet_-Y

9. W_PH_+X
10. W_PH_-X
11. W_PH_+Y
12. W_PH_-Y

13. W_Mech_+X
14. W_Mech_-X
15. W_Mech_+Y
16. W_Mech_-Y

17. W_Ecc_+X
18. W_Ecc_-X
19. W_Ecc_+Y
20. W_Ecc_-Y

## General Workflow


1. Import model data
    a. Group definitions
2. Get pressure values from the pressure module
    a. Decide which pressure values to use??
3. Start in X+ loading direction
    WALLS:
    a. That makes X+ wall group the windward wall group
        i. Break into stories
    b. That makes X- wall group the leeward wall group
    c. That makes Y+ and Y- wall group the side wall group
    PARAPET: 
    a. That makes X+ parapet group the windward parapet group
    b. That makes X- parapet group the leeward parapet group
    c. That makes Y+ and Y- parapet group the side parapet group
        - NOTE: these get the same pressures as the side +Y & -Y wall pressures
    PENTHOUSE:
    a. That makes the X+ penthouse group the windward penthouse group
        - NOTE: only the windward group gets wind pressures
4. Repeat for X- loading direction
5. Repeat for Y+ loading direction
6. Repeat for Y- loading direction
