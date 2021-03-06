"""Calculate data statistics once and stores."""
import os
import click
import logging
from glob import glob
from smartink.data.stroke_dataset import TFRecordStroke

@click.command()
@click.option('--data_dir', default='data', help='Path to data (default: data)')
@click.option('--log_level', default='INFO', help='Log level (default: INFO)')
def main(data_dir, log_level):

    log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=log_level, format=log_fmt)

    # Setup and settings.
    if "COSE_data_dir" in os.environ:
      data_dir = os.path.join(os.environ["COSE_DATA_DIR"], "didi_wo_text/")
    else:
      data_dir = os.path.join(data_dir, "didi_wo_text/")

    TFRECORD_PATTERN = "diagrams_wo_text_20200131-*-of-*"
    META_FILE = "didi_wo_text-stats-origin_abs_pos.npy"

    data_paths = glob(os.path.join(data_dir, "training", TFRECORD_PATTERN))
    logging.info("Located data files:\n{}".format('\n'.join(data_paths)))

    USE_POSITION = True  # Calculate statistics for pixel coordinates (i.e. absolute positions) or relative offsets (i.e., velocity).
    MAX_LENGTH = 301  # Longer or shorter strokes will be filtered out.
    MIN_LENGTH = 2

    logging.info("Saving metadata to: {data_dir + META_FILE}")
    train_data = TFRecordStroke(
        data_path=data_paths,
        meta_data_path=data_dir + META_FILE,
        pp_to_origin=USE_POSITION,
        pp_relative_pos=not USE_POSITION,
        max_length_threshold=MAX_LENGTH,
        min_length_threshold=MIN_LENGTH,
        normalize=True,
        batch_size=1,
        shuffle=False,
        run_mode="eager",
        fixed_len=False,
        mask_pen=False,
        scale_factor=0,
        resampling_factor=0,
        random_noise_factor=0,
        gt_targets=False,
        n_t_targets=1,
        concat_t_inputs=False,
        reverse_prob=0,
        t_drop_ratio=0,
        affine_prob=0
        )


if __name__ == "__main__":
    main()
