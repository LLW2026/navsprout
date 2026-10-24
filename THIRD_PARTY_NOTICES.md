# Third-party notices

## Background photographs

The JPEG photographs in `app/static/backgrounds/` are **not** licensed under the project MIT License. They were obtained through [Lorem Picsum](https://picsum.photos/) and remain subject to the [Unsplash License](https://unsplash.com/license). This license allows free personal and commercial use, with restrictions on selling unmodified photographs and compiling a competing image service.

Each photograph's author, original work URL and license URL are recorded in [catalog.json](app/static/backgrounds/catalog.json). Runtime photographs retain equivalent metadata in the private background cache. The application shows the current photographer and work link in its footer.

## Dependencies

Python and Node dependencies retain their respective upstream licenses. They are installed by the package managers and are not vendored into this repository. Node / Playwright is used only for development and browser checks; the deployed frontend uses local JavaScript and CSS.

The application's favicon and interface code are covered by the project MIT License.
