"""Which editions exist, and which day each one sends."""

from editions.preview import PreviewEdition

# Slug -> class. The slug is also the archive folder, the template name
# and the CLI argument.
EDITIONS = {
    PreviewEdition.name: PreviewEdition,
}

# ISO weekday (Mon=1) -> edition that sends that day. Editions that are
# not built yet are simply absent; the workflow runs `auto` every weekday
# and the runner consults this, so adding an edition here is what
# schedules it.
WEEKDAY_EDITIONS = {
    5: "preview",
}
