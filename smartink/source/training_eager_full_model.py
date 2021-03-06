"""Training engine in eager mode."""

import os

import time
import numpy as np
import tensorflow as tf

from smartink.util.learning_rate import LearningRateFactory
from smartink.util.utils import AggregateAvg
from smartink.util.utils import dict_tf_to_numpy
from common.logger import GoogleSheetLogger


class TrainingEngine(object):
  """Provides basic training and evaluation loop for debugging in eager mode."""

  def __init__(self,
               config,
               model,
               train_data,
               valid_data,
               test_data=None,
               debug=False):

    self.config = config
    self.model = model
    self.train_data = train_data
    self.valid_data = valid_data
    self.test_data = test_data
    self.debug = debug

    self.model_dir = config.experiment.model_dir
    self.max_steps = config.experiment.max_steps
    self.checkpoint_frequency = config.experiment.checkpoint_frequency
    self.log_frequency = config.experiment.log_frequency

    # Create Tensorflow Routines.
    self.learning_rate_stroke_ae = LearningRateFactory.get(config.experiment.learning_rate)
    self.optimizer_stroke_ae = tf.keras.optimizers.Adam(learning_rate=self.learning_rate_stroke_ae)
    self.learning_rate_emb_pred = LearningRateFactory.get(config.experiment.learning_rate)
    self.optimizer_emb_pred = tf.keras.optimizers.Adam(learning_rate=self.learning_rate_emb_pred)
    self.learning_rate_pos_pred = LearningRateFactory.get(config.experiment.learning_rate)
    self.optimizer_pos_pred = tf.keras.optimizers.Adam(learning_rate=self.learning_rate_pos_pred)
    self.step = tf.Variable(0, name="global_step", trainable=False)
    self.epoch = tf.Variable(0, name="global_epoch", trainable=False)
    self.model.set_step(self.step)
    self.model.embedding_model.set_step(self.step)
    
    self.pretrained_emb_dir = config.experiment.get("pretrained_emb_dir", None)
    self.train_embedding_model = self.pretrained_emb_dir is None

    self.checkpoint = tf.train.Checkpoint(
        optimizer=self.optimizer_stroke_ae,
        optimizer_emb=self.optimizer_emb_pred,
        optimizer_pos=self.optimizer_pos_pred,
        model=self.model,
        # position_model=self.model.position_model,
        # embedding_model=self.model.embedding_model,
        # prediction_model=self.model.predictive_model,
        global_step=self.step)
    
    self.saver = tf.train.CheckpointManager(
        self.checkpoint,
        directory=self.model_dir,
        max_to_keep=1,
        checkpoint_name='model.ckpt')
    
    # Logging experiment results to google sheet.
    if config.get("gdrive", False):
      self.glogger = GoogleSheetLogger(
          # tf.gfile.Open(config.gdrive.credential, "r"),
          tf.io.gfile.GFile(config.gdrive.credential, "r"),
          config.gdrive.workbook, [config.gdrive.sheet + "/valid"],
          config.experiment.id,
          static_values={
              "Model ID": config.experiment.id,
              "Model Name": config.experiment.tag,
              "Comment": config.experiment.comment
          })
    else:
      self.glogger = None

  @tf.function(experimental_relax_shapes=True)
  def eval_step_static(self, batch_inputs, batch_targets):
    predictions = self.model(inputs=batch_inputs, training=False)
    loss_dict = self.model.loss(predictions, batch_targets)
    return loss_dict
  
  @tf.function(experimental_relax_shapes=True)
  def train_step_static(self, batch_inputs, batch_targets):
    with tf.GradientTape() as tape:
      predictions = self.model(inputs=batch_inputs, training=True)
      loss_dict = self.model.loss(predictions, batch_targets, training=True)

      if self.train_embedding_model:
        grads = tape.gradient(loss_dict["loss"], {"stroke_ae":self.model.embedding_model.trainable_variables, "emb_pred":self.model.predictive_model.trainable_variables, "pos_pred":self.model.position_model.trainable_variables})

        grads_params = self.grad_clip(self.model.embedding_model.trainable_variables, grads["stroke_ae"])
        self.optimizer_stroke_ae.apply_gradients(grads_params)
      else:
        grads = tape.gradient(loss_dict["loss"], {"emb_pred":self.model.predictive_model.trainable_variables, "pos_pred":self.model.position_model.trainable_variables})

    grads_params_pred = self.grad_clip(self.model.predictive_model.trainable_variables, grads["emb_pred"])
    self.optimizer_emb_pred.apply_gradients(grads_params_pred)
    
    grads_params_pos = self.grad_clip(self.model.position_model.trainable_variables, grads["pos_pred"])
    self.optimizer_pos_pred.apply_gradients(grads_params_pos)
    return loss_dict

  def train_step_eager(self, batch_inputs, batch_targets):
    with tf.GradientTape() as tape:
      predictions = self.model(inputs=batch_inputs, training=True)
      loss_dict = self.model.loss(predictions, batch_targets, training=True)
      
      if self.train_embedding_model:
        grads = tape.gradient(loss_dict["loss"], {"stroke_ae":self.model.embedding_model.trainable_variables, "emb_pred":self.model.predictive_model.trainable_variables, "pos_pred":self.model.position_model.trainable_variables})

        grads_params = self.grad_clip(self.model.embedding_model.trainable_variables, grads["stroke_ae"])
        self.optimizer_stroke_ae.apply_gradients(grads_params)
      else:
        grads = tape.gradient(loss_dict["loss"], {"emb_pred":self.model.predictive_model.trainable_variables, "pos_pred":self.model.position_model.trainable_variables})

    grads_params_pred = self.grad_clip(self.model.predictive_model.trainable_variables, grads["emb_pred"])
    self.optimizer_emb_pred.apply_gradients(grads_params_pred)
    
    grads_params_pos = self.grad_clip(self.model.position_model.trainable_variables, grads["pos_pred"])
    self.optimizer_pos_pred.apply_gradients(grads_params_pos)
    return loss_dict
  
  def grad_clip(self, parameters, gradients):
    # Gradient clipping.
    if self.config.experiment.grad_clip_value > 0:
      g = self.config.experiment.grad_clip_value
      clipped = []
      for grad, param in zip(gradients, parameters):
        if grad is not None:
          clipped.append((tf.clip_by_value(grad, -g, g), param))
      grads_params = clipped
  
    elif self.config.experiment.grad_clip_norm > 0:
      gradients, _ = tf.clip_by_global_norm(gradients,
                                            self.config.experiment.grad_clip_norm)
      grads_params = zip(gradients, parameters)
    else:
      grads_params = zip(gradients, parameters)
    return grads_params
  
  @classmethod
  def count_params(cls, parameters):
    return np.array([np.prod(w.shape) for w in parameters]).sum()

  def run(self):
    """Starts training loop."""
    print("Running Training Loop.")

    if self.debug:
      train_step_fn = self.train_step_eager
    else:
      train_step_fn = self.train_step_static

    if self.saver.latest_checkpoint:
      self.checkpoint.restore(self.saver.latest_checkpoint)
      print("Loading model {}".format(self.saver.latest_checkpoint))

    # tf.keras restores weights only after the first call.
    batch_inputs, batch_targets = self.train_data.get_next()
    _ = self.model(inputs=batch_inputs, training=True)

    # Restore the embedding model only.
    if self.pretrained_emb_dir is not None:
      partial_checkpoint = tf.train.Checkpoint(embedding_model=self.model.embedding_model)
      embedding_checkpoint = tf.train.Checkpoint(model=partial_checkpoint)
      embedding_checkpoint_path = tf.train.latest_checkpoint(self.pretrained_emb_dir)
      if embedding_checkpoint_path is None:
        raise Exception("Checkpoint not found.")
      else:
        print("Loading embedding model " + embedding_checkpoint_path)

      emb_weights_before = self.model.embedding_model.trainable_variables[0][0, 0:3].numpy()
      pred_weights_before = self.model.predictive_model.trainable_variables[0][0, 0:3].numpy()
      embedding_checkpoint.restore(embedding_checkpoint_path).assert_existing_objects_matched()
      self.step.assign(0)
      emb_weights_after = self.model.embedding_model.trainable_variables[0][0, 0:3].numpy()
      pred_weights_after = self.model.predictive_model.trainable_variables[0][0, 0:3].numpy()
      # Sanity check.
      assert np.all(emb_weights_before != emb_weights_after), "Embedding model weights are not restored: {} vs. {}".format(emb_weights_before, emb_weights_after)
      assert np.all(pred_weights_before == pred_weights_after), "Prediction model weights changed: {} vs. {}".format(pred_weights_before, pred_weights_after)

    print("# of Total Parameters: " + str(self.model.count_params()))
    print("# of Stroke Auto-encoder Parameters: " + str(self.count_params(self.model.embedding_model.trainable_variables)))
    print("# of Embedding Prediction Parameters: " + str(self.count_params(self.model.predictive_model.trainable_variables)))
    print("# of Position Prediction Parameters: " + str(self.count_params(self.model.position_model.trainable_variables)))
    
    if self.glogger:
      self.glogger.set_static_cells({"parameters": self.model.count_params()})

    eval_loss_summary = AggregateAvg()
    
    # Early stopping configuration.
    improvement_ratio = 0.0001
    best_valid_loss = np.inf
    num_steps_wo_improvement = 0
    early_stopping_tolerance = 40

    # Run Training Loop.
    stop_signal = False
    step = 0
    while not stop_signal:
      # Training.
      for _ in range(self.checkpoint_frequency):
        try:
          self.step.assign_add(1)
          step = self.step.numpy()
          
          start_time = time.perf_counter()
          batch_inputs, batch_targets = self.train_data.get_next()

          loss_dict = train_step_fn(batch_inputs, batch_targets)

          if step % self.log_frequency == 0:
            time_elapsed = (time.perf_counter() - start_time)
            self.model.log_loss(
                loss_dict,
                prefix="Train [{:05d}] \t".format(step),
                suffix="time/batch = {:.3f}".format(time_elapsed))

        except tf.errors.OutOfRangeError:
          self.train_data.make_one_shot_iterator()
          self.epoch.assign_add(1)
      
      if step >= self.max_steps:
        print("End of Training.")
        break

      # Evaluation: make a full pass on the evaluation data.
      start_time = time.perf_counter()
      try:
        while True:
          batch_inputs_valid, batch_target_valid = self.valid_data.get_next()
          # predictions = self.model(inputs=batch_inputs_valid, training=False)
          # loss_dict_valid = self.model.loss(predictions, batch_target_valid)
          loss_dict_valid = self.eval_step_static(batch_inputs_valid, batch_target_valid)
          eval_loss_summary.add(dict_tf_to_numpy(loss_dict_valid))

      except tf.errors.OutOfRangeError:
        self.valid_data.make_one_shot_iterator()

      eval_loss_dict, eval_step = eval_loss_summary.summary_and_reset()
      self.model.log_loss(
          eval_loss_dict,
          prefix="Valid [{:05d}] \t".format(step),
          suffix="time/batch = {:.3f}".format(
              (time.perf_counter() - start_time)/eval_step))

      # Early stopping check.
      valid_loss = eval_loss_dict["loss"]
      # valid_loss = eval_loss_dict["reconstruction_stroke"]
      # valid_loss += eval_loss_dict.get("reconstruction_embedding_kld", 0.0)
      
      if (best_valid_loss - valid_loss) > np.abs(
          best_valid_loss*improvement_ratio):
        num_steps_wo_improvement = 0
      else:
        num_steps_wo_improvement += 1
      if num_steps_wo_improvement == early_stopping_tolerance:
        stop_signal = True

      if valid_loss <= best_valid_loss:
        if self.glogger:
          eval_loss_dict["step"] = step
          self.glogger.update_or_append_row(eval_loss_dict)
  
        best_valid_loss = valid_loss
  
        # tf Checkpoint API
        print("Saving checkpoint {} to {}".format(step, self.model_dir))
        self.saver.save(checkpoint_number=self.step)

    # Restore the best checkpoint and save in saved_model format for deployment.
    self.checkpoint.restore(self.saver.latest_checkpoint)
    print("Loading model {}".format(self.saver.latest_checkpoint))
    batch_inputs, batch_targets = self.train_data.get_next()
    _ = self.model(inputs=batch_inputs, training=True)
    
    if self.config.get("predictive_model", None) is not None:
      # Full model.
      _ = self.model.predict_on_batch(batch_inputs)
      _ = self.model.embedding_model.predict_on_batch(batch_inputs)
      
      self.model.save(
        os.path.join(self.model_dir, "saved_model_with_signatures"),
        signatures={"decode_stroke"    : self.model.embedding_model.serving_decode_strokes,
                    "encode_stroke"    : self.model.embedding_model.serving_encode_strokes,
                    "forward_pass"     : self.model.embedding_model.serving_forward_pass,
                    "predict_embedding": self.model.serving_predict_embedding,
                    "predict_position" : self.model.serving_predict_position,
                    })
    else:
      # Embedding model only.
      _ = self.model.predict_on_batch(batch_inputs)

      # decoding_signature = self.model.decode_single_stroke.get_concrete_function(
      #   embedding=tf.TensorSpec(shape=[None, 8], dtype=tf.float32),
      #   seq_len=tf.TensorSpec(shape=(), dtype=tf.int32))
      #
      # encoding_signature = self.model.encode_single_stroke.get_concrete_function(
      #     input_stroke=tf.TensorSpec(shape=[None, None, 3], dtype=tf.float32),
      #     seq_len=tf.TensorSpec(shape=[None], dtype=tf.int32))
      
      self.model.save(os.path.join(self.model_dir, "saved_model_with_signatures"),
                      signatures={"decode_stroke": self.model.serving_decode_strokes,
                                  "encode_stroke": self.model.serving_encode_strokes,
                                  "forward_pass": self.model.serving_forward_pass,
                                  })
      """
      cd [model directory]
      tensorflowjs_converter ./saved_model_with_signatures ./js_encoder --input_format=tf_saved_model  --saved_model_tags=serve --signature_name encode_stroke
      tensorflowjs_converter ./saved_model_with_signatures ./js_decoder --input_format=tf_saved_model  --saved_model_tags=serve --signature_name decode_stroke
      tensorflowjs_converter ./saved_model_with_signatures ./js_embedding_predictor --input_format=tf_saved_model  --saved_model_tags=serve --signature_name predict_embedding
      tensorflowjs_converter ./saved_model_with_signatures ./js_position_predictor --input_format=tf_saved_model  --saved_model_tags=serve --signature_name predict_position
      """
      