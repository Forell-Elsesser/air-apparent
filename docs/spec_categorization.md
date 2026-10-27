## Shell-group distinctions

Each shell group is assigned from five independent distinctions. Together they identify the load case without relying on a single overloaded label:

1. **Wind direction** — the global direction of the applied wind, such as `+X`, `-X`, `+Y`, or `-Y`.
2. **Element type** — the physical component receiving the load, such as a wall, parapet, or mechanical screen/equipment.
3. **Wind loading type** — how the component is loaded, such as windward, leeward, or mechanical/equipment loading.
4. **Side relative to the center** — the component's location relative to the building center of gravity or a defined grid-line side (for example, left/right or north/south). Use grid lines where they provide a clearer, repeatable boundary.
5. **Level** — the story or elevation containing the component, such as the first story or roof.

The assignment logic is: determine the wind direction, identify the element, classify the loading behavior, locate the element relative to the center/grid, and then assign its level. A group should contain only components with the same five values; if any value changes, create a separate group.


## General Workflow

1. Import model data
    a. Grid defs and story defs
    c. Shell unique names

2. For each direction:
    a. Select windward direction
    b. Find shells on windward direction grid line