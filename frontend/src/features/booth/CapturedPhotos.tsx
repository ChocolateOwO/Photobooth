import type { ShotState } from '../../shared/api/client'
import styles from './CapturedPhotos.module.css'

/**
 * The photos taken so far: one small place per shot, in order, along the edge of the screen.
 *
 * Every shot of the chosen frame has its own place. A place stays empty until its own photo
 * arrives: a picture is only ever shown under its own number, so nobody can mistake one photo
 * for another. While the photos are being taken, pressing one opens it large; on the review
 * screen, pressing one chooses which photo the big picture shows.
 */

interface CapturedPhotosProps {
  shots: ShotState[]
  /** The photo of one shot, for an <img>; null while that shot has none. */
  photoUrl: (shot: ShotState) => string | null
  /** The participant pressed this shot's place. */
  onPick: (shot: ShotState, opener: HTMLButtonElement) => void
  /** Review: the shot the big picture is showing, so its place is marked as chosen. */
  selected?: number | undefined
  /** Review: pressing a place chooses it rather than opening it. */
  select?: boolean
  /** Show the photos the way the print will have them (the event's mirror setting). */
  mirror?: boolean
}

export function CapturedPhotos({
  shots,
  photoUrl,
  onPick,
  selected,
  select = false,
  mirror = false,
}: CapturedPhotosProps) {
  return (
    <ul className={styles.strip} aria-label="Photos taken" data-testid="captured-photos">
      {shots.map((shot) => {
        const url = photoUrl(shot)
        const chosen = select && selected === shot.shot_index
        return (
          <li key={shot.shot_index} className={styles.slot} data-testid="captured-photo">
            {url ? (
              <button
                type="button"
                className={styles.photoButton}
                data-chosen={chosen ? '' : undefined}
                {...(select ? { 'aria-pressed': chosen } : {})}
                aria-label={
                  select ? `Show photo ${shot.shot_index}` : `Photo ${shot.shot_index}, see it bigger`
                }
                onClick={(event) => onPick(shot, event.currentTarget)}
              >
                <img
                  src={url}
                  alt={`Photo ${shot.shot_index}`}
                  className={styles.photo}
                  data-mirrored={mirror ? '' : undefined}
                />
              </button>
            ) : (
              // Nothing here yet: an empty place, never another shot's picture.
              <span className={styles.empty} aria-label={`Photo ${shot.shot_index}, not taken yet`} />
            )}
            <span className={styles.label}>Photo {shot.shot_index}</span>
          </li>
        )
      })}
    </ul>
  )
}
