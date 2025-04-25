# Changelog

c3nav does not exactly have a versioning scheme. 

This file aims to give you an idea of what has changed between events where c3nav was used or supported by the
development team. These lists do not aim to be complete but help you get an overview about the most iportant changes
and potential backwards incompatibilities.

# New Location Hierarchy branch

Location tags:

- Previously, Locations were either Specific Locations, which would be Levels, Spaces, Areas, POIs or Dynamic Locations,
  or a Location Group. This entire concept has been removed. Updating will migrate your data.
- Now, there are only Locations and Location Targets. 
- A location can be a Custom Location (coordinates), a (moving) Position or a Location Tag.
- A location target can be a Level, Space, Area, POI or Dynamic Location Tag Target (which links to a Position).
- Location tags become a acyclic directed graph, meaning every location tag can have multiple parents.
- A location tags can point to 0-* Location Targets
- Specific Locations, Location Groups and Location Group Categories have all been converted to Defined Locations.
- Inheritable attributes like color get inherited from the highest priority parent.
- For search, locations tags are ranked by depth first, priority second.
- Searching for a Location tag with children will match all of its descendant's targets,
  which means you can now easily Group locations based on Purpose, Building Section, Building, Event, …
- Location Targets can belong to more than one location. This makes it possible to have, for example,
  two locations for one Space, one being the Room Number given by the building and another one being the Name
  given to it by the event.
- The next step after this restructuring is to restructure geometries/location targets.
- Some improvements in the Editor to deal with this new model are still on the way.
- A lot of things were changed to make this restructuring possible, overhauling, modernizing and improving a lot of
  code on the way.

Big stuff:

- Processupdates is now divided into different jobs. This makes it possible for some parts
  of its results to be used before all of it has run throguh, as well as paralelization of 
  the work being done.
- The API has changed in many places, the location API is much more unified,
  and easier to use. We focused keeping changes in a level where it will not be hard
  to adapt your code.
- Map permissions are now tracked using a context manager, enhancing security and clearing
  up the code base. In most places, we now cache special objects that can filter lists or
  modify values efficiently on the fly for the correct permission set.
- Many things are now cached in the databse or cached more efficiently and with less duplicates, 
  which should improve response times and memory footprint. We plan to make cache keys / E-tags more
  granular in the future to improve peformance and data usage.
- Many things that used to be generated and cached on the first page load, are now generated and 
  cached by processupdates.
- Geometries will now be correctly cropped to spaces etc when highlighted on the map.
- A lot more type hinting in the codebase, much code modernizatino.
- A lof of old serialization code has been removed, we use pydantic more directly now. Thanks to multi-model 
  inheritance being gone the entire code base and inheritance is now easier to understand. 

Semi-big stuff:

- Maximum bounds on the public front-end is now determined by the maximum bounds of
  the rendered area, not the maximum Source bounds.
- Fix some bugs in how routes were rendered in the front end (point overrides).

Behind the scenes, comfort, bug fixes:

- Storing lists of access permissions in a compressed binary format for cache keys, meaning no more need
  for hashing cause the values are short and reducing the likeliness of already unlikely collisions.


# Eurofurence 29 ([ef29](https://github.com/c3nav/c3nav/tree/ef28))

- Fix Problem with fetch updates API
- Fix issues with localcontext in main UI
- Some updates to accomodate theming
- Fix SSO strategy imports
- Fix router preview not being themed
- New quest to look at known WiFi AP
- Experimental support for scanning for BLE iBeacons through native brower APIs
- Experimental support for mapping out media panels / network panels

# Easterhegg 2025 ([eh2025](https://github.com/c3nav/c3nav/tree/eh2025))

Behind the scenes, comfort, bug fixes:

- fix bug that prevented the UI from working when no overlays were configured
- add instance name to sentry bug reports
- avoid excessive number of queries in the theme code during every request
- rip out awful old Editor API that hopefully noone ever used
- finally tracked down the bug locking the entire map while processupdates was running,
  meaning you can not continue using the editor while processupdates is running.
- better type hinting in some places
- fix bug introduced 4 months ago that allowed users with access to the editor to
  self-review changesets so long if they only created objects within spaces
- fix very persistent theme color caching issues  

# 38. Chaos Communication Congress ([38c3](https://github.com/c3nav/c3nav/tree/38c3))

Big stuff:

- Quest support to categorize rooms, find AP altitudes, AP names, do wifi scanning and generate route descriptions
- data overlay support
- complete rewrite of editor changesets as a base for a more modern editor – you will lose all changesets!
- new map settings API endpoint
- ability to import APs from NOC eventmap
- ability to import Antennas from POC
- introducing load groups, a way to display how crowded certain parts of the map are based on statistics from WiFi APs
- new positioning algorithm based on AP positions, not very good but results look convincing
- overlay to show all your own moving positions

Semi-big stuff:

- "show nearby" is now clustered for points too close together
- Doors now have a UI to easily manage edges that go through them, as well as a To Do feature
- space can now be classified as "identifyable" to determine which route descriptions they need
- reports for wrong locations can now be auto-rejected based on location g
- access restrictions that are part of an access restriction group are now defined in the group, data was migrated
- editor access restriction overview now highlights affected spaces on a map
- editor access restriction group edit now shows spaces with selected access restrictions and allows selecting through double click
- WayTypes can now be excluded by default
- Pass route options through url parameter
- support for various SSOs
- various compliance checkboxes
- support for importing projects and rooms from hub
- match APs using name broadcast in Aruba vendor-data instead of just BSSIDs
- fewer and more performant calls to redis
- pruning redis cache automatically after a new map update is created

Small stuff:

- Fix bug where it hasn't been possible since ages to link to POIs without a slug
- External URLs is now shown more prominently, with a custom label and can now also be set for location groups
- Level short_label has been split into short_label (for displaying) and level_index (for internal use like coordinates)
- some API mapdata endpoints were moved, some lesser used properties renamed
- proper support for access restricted levels
- ability to store mutiple BSSIDs per beacon
- importhub can now import projects and rooms as well

Behind the scenes, comfort, bug fixes:

- positioning/beacon measurements now have schemas
- more type hinting and code modernization 
- paste in slug field is now auto-lowercase
- fix editor header on mobile
- some js refactors in main UI

# Eurofurence 28 ([ef28](https://github.com/c3nav/c3nav/tree/ef28))

- map key/legend including settings for it in the editor
- SSO support for access permission management
- bring back buttons to set moving positions
- fix "show nearby"
- more advanced theming support
- prometheus updates
- UwU support

# Håck ma's Castle 2024 ([hackmas2024](https://github.com/c3nav/c3nav/tree/hackmas2024))

- GPS support for positioning, support for defining a proj4 conversion string
- turn "click anywhere" into a one-step process to make options more obvious
- ramps can now have more than two altitudes and will be interpolated correctly, important for terrain
- fixed redemption of signed access permission tokens 

# Easterhegg 2024 ([eh2024](https://github.com/c3nav/c3nav/tree/eh2024))

- theming support (introduces ObstacleGroups for colors, automatic data migration)
- reports for missing locations can now be auto-rejected based on location groups
- prometheus statistics export
- more mesh support, still not done
- create a step/question based report flow process
- some fixes to editor changesets

# 37. Chaos Communication Congress ([37c3](https://github.com/c3nav/c3nav/tree/37c3))

- new OpenAPI-Compatible RESTful API v2
- ground altitudes are now defined separately and can be re-used, data will be migrated automatically
- rich links previews when sharing links to c3nav
- editor SVG sources support
- basic support for WiFi RTT measurements
- imprint is now configured differently/externally
- support for unlimited access permission tokens
- import function from the c3 hub for assemblies and similar
- areas can now have a main_point (only relevant for hub import, not available in the editor yet)
- migrated from material icons to material symbols
- levels do no longer need at least one hole to render properly
- support PWA and native sharing functionalities
- some modernization of front-end code, based on the new API, TypeScript support
- initial c3nav mesh support for locator beacons (not finished)
- modernized rendering code
- zstd compression support for communication with tile server
- updated docker deployment
- ASGI support