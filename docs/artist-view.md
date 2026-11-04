# Artist view

The **Artists** tab shows a name-searchable list and, on the right, the selected artist's albums sorted by year and title. Each edition retains its folder and tracks. Open details with **View album**, double-click or Enter; the usual editing and tag writing actions are available there. **Artists** is the initial tab.

The header displays a JPG/JPEG from the parent folder of the artist's albums, without searching subfolders. Priority is `artist.jpg`, then `folder.jpg`, then alphabetical filename order (case-insensitive extensions). Multiple folders are visited in path order. If no image is available, the header has no photo. Reading runs in the background when selecting an artist or reloading the view; this image is neither embedded in songs nor saved in the catalog.

Grouping uses album artists. Albums with multiple credited artists appear under each one. When album credits are missing, track artists are used only if identical across every song. Other albums appear under **No album artist**, without attributing a compilation to each guest. Names are not split on commas or other separators, and variants are not merged.

The view uses saved catalog data and works without audio files. Entering the tab or refreshing the catalog reloads the list while preserving the search and selected artist when still available. Grouping does not modify metadata or create additional records.
