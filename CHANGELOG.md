# Changelog

c3nav does not exactly have a versioning scheme. 

This file aims to give you an idea of what has changed between events where c3nav was used or supported by the
development team. These lists do not aim to be complete but help you get an overview about the most iportant changes
and potential backwards incompatibilities.

# 38. Chaos Communication Congress (development ongoing)

- data overlay support
- complete rewrite of editor changesets as a base for a more modern editor – you will lose all changesets!
- new map settings API endpoint
- some API mapdata endpoints were moved, some lesser used properties renamed
- reports for wrong locations can now be auto-rejected based on location groups
- access restrictions that are part of an access restriction group are now defined in the group, data was migrated
- editor access restriction overview now highlights affected spaces on a map
- editor access restriction group edit now shows spaces with selected access restrictions and allows selecting through double click
- WayTypes can now be excluded by default

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