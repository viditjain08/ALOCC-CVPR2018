from __future__ import division
from tensorflow.examples.tutorials.mnist import input_data
import re
from ops import *
from utils import *
from kh_tools import *
import logging
import matplotlib.pyplot as plt

class ALOCC_Model(object):
  def __init__(self, sess,
               input_height=45,input_width=45, output_height=64, output_width=64,
               batch_size=64, sample_num = 64, attention_label=1, is_training=True,
               z_dim=100, gf_dim=16, df_dim=16, gfc_dim=512, dfc_dim=512, c_dim=3,
               dataset_name=None, dataset_address=None, input_fname_pattern=None,
               checkpoint_dir=None, log_dir=None, sample_dir=None, r_alpha = 0.2,
               kb_work_on_patch=True, nd_input_frame_size=(240, 360), nd_patch_size=(10, 10), n_stride=1,
               n_fetch_data=10, n_per_itr_print_results=500):
    """
    This is the main class of our Adversarially Learned One-Class Classifier for Novelty Detection
    :param sess: TensorFlow session
    :param batch_size: The size of batch. Should be specified before training. [128]
    :param attention_label: Conditioned label that growth attention of training label [1]
    :param r_alpha: Refinement parameter [0.2]
    :param z_dim:  (optional) Dimension of dim for Z. [100]
    :param gf_dim: (optional) Dimension of gen filters in first conv layer. [64]
    :param df_dim: (optional) Dimension of discrim filters in first conv layer. [64]
    :param gfc_dim: (optional) Dimension of gen units for for fully connected layer. [1024]
    :param dfc_dim: (optional) Dimension of discrim units for fully connected layer. [1024]
    :param c_dim: (optional) Dimension of image color. For grayscale input, set to 1. [3]
    :param sample_dir: Directory address which save some samples [.]
    :param kb_work_on_patch: Boolean value for working on PatchBased System or not [True]
    :param nd_input_frame_size:  Input frame size
    :param nd_patch_size:  Input patch size
    :param n_stride: PatchBased data preprocessing stride
    :param n_fetch_data: Fetch size of Data
    :param n_per_itr_print_results: # of printed iteration
    """

    self.n_per_itr_print_results=n_per_itr_print_results
    self.nd_input_frame_size = nd_input_frame_size
    self.b_work_on_patch = kb_work_on_patch
    self.sample_dir = sample_dir

    self.sess = sess
    self.is_training = is_training

    self.r_alpha = r_alpha

    self.batch_size = batch_size
    self.sample_num = sample_num

    self.input_height = input_height
    self.input_width = input_width
    self.output_height = output_height
    self.output_width = output_width

    self.z_dim = z_dim

    self.gf_dim = gf_dim
    self.df_dim = df_dim

    self.gfc_dim = gfc_dim
    self.dfc_dim = dfc_dim

    # batch normalization : deals with poor initialization helps gradient flow
    self.d_bn0 = batch_norm(name='d_bn0')
    self.d_bn1 = batch_norm(name='d_bn1')
    self.d_bn2 = batch_norm(name='d_bn2')
    self.d_bn3 = batch_norm(name='d_bn3')

    self.g_bn0 = batch_norm(name='g_bn0')
    self.g_bn1 = batch_norm(name='g_bn1')
    self.g_bn2 = batch_norm(name='g_bn2')
    self.g_bn3 = batch_norm(name='g_bn3')
    self.g_bn4 = batch_norm(name='g_bn4')
    self.g_bn5 = batch_norm(name='g_bn5')
    self.g_bn6 = batch_norm(name='g_bn6')
    self.g_bn7 = batch_norm(name='g_bn7')

    self.dataset_name = dataset_name
    self.dataset_address= dataset_address
    self.input_fname_pattern = input_fname_pattern
    self.checkpoint_dir = checkpoint_dir
    self.log_dir = log_dir

    self.attention_label = attention_label

    if self.is_training:
      logging.basicConfig(filename='ALOCC_loss.log', level=logging.INFO)

    if self.dataset_name == 'mnist':
      mnist = input_data.read_data_sets(self.dataset_address)
      specific_idx = np.where(mnist.train.labels == self.attention_label)[0]
      self.data = mnist.train.images[specific_idx].reshape(-1, 28, 28, 1)
      self.c_dim = 1
    elif self.dataset_name == 'UCSD':
      self.nStride = n_stride
      self.patch_size = nd_patch_size
      self.patch_step = (n_stride, n_stride)
      lst_image_paths = []
      for s_image_dir_path in glob(os.path.join(self.dataset_address, self.input_fname_pattern)):
        for sImageDirFiles in glob(os.path.join(s_image_dir_path+'/*')):
          lst_image_paths.append(sImageDirFiles)
      self.dataAddress = lst_image_paths
      lst_forced_fetch_data = [self.dataAddress[x] for x in random.sample(range(0, len(lst_image_paths)), n_fetch_data)]

      self.data = lst_forced_fetch_data
      self.c_dim = 1
    else:
      assert('Error in loading dataset')

    self.grayscale = (self.c_dim == 1)
    self.build_model()

  # =========================================================================================================
  def build_model(self):

    image_dims = [self.input_height, self.input_width, self.c_dim]

    self.inputs = tf.placeholder(tf.float32, [self.batch_size] + image_dims, name='real_images')
    self.sample_inputs = tf.placeholder(tf.float32, [self.sample_num] + image_dims, name='sample_inputs')

    inputs = self.inputs
    sample_inputs = self.sample_inputs

    # tesorboard setting
    # self.z_sum = histogram_summary("z", self.z)
    # self.d_sum = histogram_summary("d", self.D)
    # self.d__sum = histogram_summary("d_", self.D_)
    # self.G_sum = image_summary("G", self.G)

    # The error function added to the image
    self.z = tf.placeholder(tf.float32,[self.batch_size] + image_dims, name='z')

    # Generate the Images
    self.G, self.G_ = self.generator(self.z)

# Generator apply sigmoid
    # Use the Discriminator to discriminate for the generator's image and the input image

    self.D, self.D_logits = self.discriminator(inputs)
    self.D_, self.D_logits_ = self.discriminator(self.G, reuse=True)

    self.sampler, self.sampler_ = self.generator(self.z,reuse=True)

    # Simple GAN's losses
    self.d_loss_real = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits, labels=tf.ones_like(self.D)))
    self.d_loss_fake = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_, labels=tf.zeros_like(self.D_)))

    # Non Saturating Heuristic
    self.g_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_, labels=tf.ones_like(self.D_)))

    # Refinement loss
    self.g_r_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.G_,labels=inputs))

    # Final Loss
    self.g_loss  = self.g_loss + self.g_r_loss * self.r_alpha * 3
    self.d_loss = self.d_loss_real + self.d_loss_fake

    self.d_loss_real_sum = tf.summary.scalar("d_loss_real", self.d_loss_real)
    self.d_loss_fake_sum = tf.summary.scalar("d_loss_fake", self.d_loss_fake)
    self.g_loss_sum = tf.summary.scalar("g_loss", self.g_loss)
    self.d_loss_sum = tf.summary.scalar("d_loss", self.d_loss)

    t_vars = tf.trainable_variables()

    self.d_vars = [var for var in t_vars if 'd_' in var.name]
    self.g_vars = [var for var in t_vars if 'g_' in var.name]


# =========================================================================================================
  def train(self, config):

    d_grads = tf.train.AdamOptimizer(config.learning_rate).compute_gradients(self.d_loss, var_list=self.d_vars)
    g_grads = tf.train.AdamOptimizer(config.learning_rate).compute_gradients(self.g_loss, var_list=self.g_vars)

    d_optim = tf.train.AdamOptimizer(config.learning_rate).apply_gradients(d_grads)
    g_optim = tf.train.AdamOptimizer(config.learning_rate).apply_gradients(g_grads)

    d_grads_scalar = []
    g_grads_scalar = []
    for grad, var in d_grads:
        d_grads_scalar.append(tf.summary.histogram(var.name + '/d_gradient', grad))
    for grad, var in g_grads:
        g_grads_scalar.append(tf.summary.histogram(var.name + '/g_gradient', grad))
    # Merge all summaries into a single op

    print(d_grads_scalar)
    print(g_grads_scalar)
    self.d_grads = merge_summary(d_grads_scalar)
    self.g_grads = merge_summary(g_grads_scalar)

    tf.global_variables_initializer().run()

    self.saver = tf.train.Saver(max_to_keep=40)

    self.g_sum = merge_summary([self.d_loss_fake_sum, self.g_loss_sum])
    self.d_sum = merge_summary([self.d_loss_real_sum, self.d_loss_sum])

    log_dir = os.path.join(self.log_dir, self.model_dir)
    if not os.path.exists(log_dir):
      os.makedirs(log_dir)

    self.writer = SummaryWriter(log_dir, self.sess.graph)

    if config.dataset == 'mnist':
      sample = self.data[0:self.sample_num]
    elif config.dataset =='UCSD':
      if self.b_work_on_patch:
        sample_files = self.data[0:10]
      else:
        sample_files = self.data[0:self.sample_num]
      sample,_ = read_lst_images(sample_files, self.patch_size, self.patch_step, self.b_work_on_patch)
      sample = np.array(sample).reshape(-1, self.patch_size[0], self.patch_size[1], 1)
      sample = sample[0:self.sample_num]

    # export images
    sample_inputs = np.array(sample).astype(np.float32)
    scipy.misc.imsave('./{}/train_input_samples.jpg'.format(config.sample_dir), montage(sample_inputs[:,:,:,0]))

    # # load previous checkpoint
    counter = 1
    could_load, checkpoint_counter = self.load(self.checkpoint_dir)
    if could_load:
      counter = checkpoint_counter
      print(" [*] Load SUCCESS")
    else:
      print(" [!] Load failed...")


    # load traning data
    if config.dataset == 'mnist':
      sample_w_noise = get_noisy_data(self.data)
    if config.dataset == 'UCSD':
      sample_files = self.data
      sample, _ = read_lst_images(sample_files, self.patch_size, self.patch_step, self.b_work_on_patch)
      sample = np.array(sample).reshape(-1, self.patch_size[0], self.patch_size[1], 1)
      sample_w_noise,_ = read_lst_images_w_noise(sample_files, self.patch_size, self.patch_step)
      sample_w_noise = np.array(sample_w_noise).reshape(-1, self.patch_size[0], self.patch_size[1], 1)

      print(sample.shape)
      print(sample_w_noise.shape)

    for epoch in xrange(config.epoch):
      print('Epoch ({}/{})-------------------------------------------------'.format(epoch,config.epoch))
      if config.dataset == 'mnist':
        batch_idxs = min(len(self.data), config.train_size) // config.batch_size
      elif config.dataset == 'UCSD':
        batch_idxs = min(len(sample), config.train_size) // config.batch_size

      # for detecting valuable epoch that we must stop training step
      # sample_input_for_test_each_train_step.npy
      sample_test = np.load('SIFTETS.npy').reshape([504,45,45,1])[0:64]

      for idx in xrange(0, batch_idxs):
        if config.dataset == 'mnist':
          batch = self.data[idx * config.batch_size:(idx + 1) * config.batch_size]
          batch_noise = sample_w_noise[idx * config.batch_size:(idx + 1) * config.batch_size]
        elif config.dataset == 'UCSD':
          batch = sample[idx * config.batch_size:(idx + 1) * config.batch_size]
          batch_noise = sample_w_noise[idx * config.batch_size:(idx + 1) * config.batch_size]

        batch_images = np.array(batch).astype(np.float32)
        batch_noise_images = np.array(batch_noise).astype(np.float32)

        batch_z = np.random.uniform(0, 1, [config.batch_size, self.z_dim]).astype(np.float32)

        if config.dataset == 'mnist':
          # Update D network
          _, summary_str,grads = self.sess.run([d_optim, self.d_sum,self.d_grads],
                                         feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          self.writer.add_summary(summary_str, counter)
          self.writer.add_summary(grads, counter)

          # Update G network
          _, summary_str,grads = self.sess.run([g_optim, self.g_sum,self.g_grads],
                                         feed_dict={self.z: batch_noise_images})
          self.writer.add_summary(summary_str, counter)
          self.writer.add_summary(grads, counter)

          # Run g_optim twice to make sure that d_loss does not go to zero (different from paper)
          _, summary_str,grads = self.sess.run([g_optim, self.g_sum, self.g_grads],
                                         feed_dict={self.z: batch_noise_images})
          self.writer.add_summary(summary_str, counter)
          self.writer.add_summary(grads, counter)


          errD_fake = self.d_loss_fake.eval({self.z: batch_noise_images})
          errD_real = self.d_loss_real.eval({self.inputs: batch_images})
          errG = self.g_loss.eval({self.z: batch_noise_images})
        else:
          # update discriminator
          # if idx%2==0:
          #     _ = self.sess.run([d_optim],
          #                                  feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          summary_str,grads = self.sess.run([self.d_sum,self.d_grads],
                                         feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          self.writer.add_summary(summary_str, counter)
          self.writer.add_summary(grads, counter)
          self.writer.flush()
          # a,b = self.sess.run([self.D,self.D_],
          #                                feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          # Update G network
          # _, summary_str,grads,c,d = self.sess.run([g_optim, self.g_sum,self.g_grads,self.D,self.D_],
          #                                feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          _, summary_str,grads,c,d = self.sess.run([g_optim, self.g_sum,self.g_grads,self.D,self.D_],
                                         feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          # _, summary_str,grads,c,d = self.sess.run([g_optim, self.g_sum,self.g_grads,self.D,self.D_],
          #                                feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          self.writer.add_summary(summary_str, counter)
          self.writer.add_summary(grads, counter)
          self.writer.flush()
          c,d = self.sess.run([self.D,self.D_],
                                         feed_dict={self.inputs: batch_images, self.z: batch_noise_images})
          errD_fake = self.d_loss_fake.eval({ self.inputs: batch_images, self.z: batch_noise_images })
          errD_real = self.d_loss_real.eval({ self.inputs: batch_images, self.z: batch_noise_images })
          errG = self.g_loss.eval({self.inputs: batch_images, self.z: batch_noise_images})

        counter += 1
        # print(self.sess.run([self.D,self.D_],feed_dict={self.inputs: batch_images, self.z: batch_noise_images}))
        msg = "Epoch:[%2d][%4d/%4d]--> Fake_d_loss: %.8f, Real_d_loss: %.8f, g_loss: %.8f" % (epoch, idx, batch_idxs, errD_fake, errD_real, errG)
        print(msg)
        logging.info(msg)
        msg = "D_real_prob: %.8f, D_fake_loss: %.8f, G_real_prob: %.8f, G_fake_loss: %.8f" % (np.mean(a),np.mean(b),np.mean(c),np.mean(d))
        print(msg)
        logging.info(msg)

        if np.mod(counter, self.n_per_itr_print_results) == 0:
          if config.dataset == 'mnist':
            samples, d_loss, g_loss, a = self.sess.run(
              [self.sampler, self.d_loss, self.g_loss, self.D_],
              feed_dict={
                  self.z: sample_inputs,
                  self.inputs: sample_inputs
              }
            )
            manifold_h = int(np.ceil(np.sqrt(samples.shape[0])))
            manifold_w = int(np.floor(np.sqrt(samples.shape[0])))
            save_images(samples, [manifold_h, manifold_w],
                  './{}/train_{:02d}_{:04d}.png'.format(config.sample_dir, epoch, idx))
            print("[Sample] d_loss: %.8f, g_loss: %.8f" % (d_loss, g_loss))
            msg = "Real Probability: %.8f" % (np.mean(a))
            print(msg)
          # ====================================================================================================
          else:
            #try:
              samples, d_loss, g_loss = self.sess.run(
                [self.sampler, self.d_loss, self.g_loss],
                feed_dict={
                    self.z: sample_inputs,
                    self.inputs: sample_inputs,
                },
              )

              # sample_test_out = self.sess.run(
              #   [self.sampler],
              #   feed_dict={
              #       self.z: sample_test
              #   },
              # )
              # export images
              scipy.misc.imsave('./{}/z_test_{:02d}_{:04d}.png'.format(config.sample_dir, epoch, idx),
                            montage(samples[:, :, :, 0]))

              # export images
              # scipy.misc.imsave('./{}/train_{:02d}_{:04d}.png'.format(config.sample_dir, epoch, idx),
              #                   montage(samples[:, :, :, 0]))

              msg = "[Sample] d_loss: %.8f, g_loss: %.8f" % (d_loss, g_loss)
              print(msg)
              logging.info(msg)
              msg = "Real Probability: %.8f" % (np.mean(a))
              print(msg)
              logging.info(msg)

      test_img = read_lst_images_w_noise2(["./dataset/UCSD_Anomaly_Dataset.v1p2/UCSDped2/Test/Test004/068.tif"], (45,45), (10,10))
      test_img_orig = read_lst_images_without_noise2(["./dataset/UCSD_Anomaly_Dataset.v1p2/UCSDped2/Test/Test004/068.tif"], (45,45), (10,10))

      test_patch,test_location = get_image_patches(test_img,(45,45), (10,10))
      test_patch_orig,test_location_orig = get_image_patches(test_img_orig,(45,45), (10,10))

      frame_test_patches = np.expand_dims(np.squeeze(test_patch),axis=-1)
      frame_test_patches_orig = np.expand_dims(np.squeeze(test_patch_orig),axis=-1)

      test_batch_idxs = len(frame_test_patches) // self.batch_size
      print(len(frame_test_patches))
      print('start new process ...')
      lst_generated_img=[]
      lst_discriminator_v=[]
      for i in xrange(0, test_batch_idxs):
          batch_data = frame_test_patches[i * self.batch_size:(i + 1) * self.batch_size]

          results_g = self.sess.run(self.G, feed_dict={self.z: batch_data})
          results_d = self.sess.run(self.D_, feed_dict={self.z: batch_data})
        #results = self.sess.run(self.sampler, feed_dict={self.z: batch_data})
        # to log some images with d values
        #for idx,image in enumerate(results_g):
        #  scipy.misc.imsave('samples/{}_{}.jpg'.format(idx,results_d[idx][0]),batch_data[idx,:,:,0])

          lst_discriminator_v.extend(results_d)
          lst_generated_img.extend(results_g)
          print('finish pp ... {}/{}'.format(i,test_batch_idxs))
    #f = plt.figure()
    #plt.plot(np.array(lst_discriminator_v))
    #f.savefig('samples/d_values.jpg')
      print(np.squeeze(np.array(lst_discriminator_v)))
      start = (test_batch_idxs-1)*self.batch_size
      end = (test_batch_idxs)*self.batch_size
      errD_fake = self.d_loss_fake.eval({ self.inputs: frame_test_patches_orig[start:end], self.z: frame_test_patches[start:end] })
      errD_real = self.d_loss_real.eval({ self.inputs: frame_test_patches_orig[start:end], self.z: frame_test_patches[start:end] })
      errG = self.g_loss.eval({self.inputs: frame_test_patches_orig[start:end], self.z: frame_test_patches[start:end]})
      msg = "Fake_d_loss: %.8f, Real_d_loss: %.8f, g_loss: %.8f" % (errD_fake, errD_real, errG)
      print(msg)

      scipy.misc.imsave('./'+self.sample_dir+'/ALOCC_generated'+str(epoch)+'.jpg', montage(np.array(lst_generated_img)[:,:,:,0]))
      scipy.misc.imsave('./'+self.sample_dir+'/ALOCC_input'+str(epoch)+'.jpg', montage(np.array(frame_test_patches)[:,:,:,0]))
      self.save(config.checkpoint_dir, epoch)

  # =========================================================================================================
  def discriminator(self, image, reuse=False):

    with tf.variable_scope("discriminator") as scope:

      if reuse:
        scope.reuse_variables()

      # df_dim = 16 (data frame dimension)
      h0 = lrelu( self.d_bn0(conv2d(image, self.df_dim*4, name='d_h0_conv')) )
      assert( h0.get_shape()[-1] == 64 )

      h1 = lrelu( self.d_bn1(conv2d(h0, self.df_dim*8, name='d_h1_conv')) )
      assert( h1.get_shape()[-1] == 128 )

      h2 = lrelu( self.d_bn2(conv2d(h1, self.df_dim*16, name='d_h2_conv')) )
      assert( h2.get_shape()[-1] == 256 )

      h3 = lrelu( self.d_bn3(conv2d(h2, self.df_dim*32, name='d_h3_conv')) )
      assert( h3.get_shape()[-1] == 512 )

      h4 = linear(tf.reshape(h3, [self.batch_size, -1]), 1, 'd_h3_lin')

      h5 = tf.nn.sigmoid(h4,name='d_output')

      return h5, h4

  # =========================================================================================================
  def generator(self, z,reuse=None):

    ''' Convolution Auto-Encoder Decoder '''

    with tf.variable_scope("generator",reuse=reuse) as scope:

      # Encoder-Architecture
      # df_dim = 16 (data frame dimension)
      encoder_0 = lrelu(self.g_bn0(conv2d(z, self.gf_dim * 4, name='g_encoder_h0_conv')))
      assert(encoder_0.get_shape()[-1] == 64)

      encoder_1 = lrelu(self.g_bn1(conv2d(encoder_0, self.gf_dim * 8, name='g_encoder_h1_conv')))
      assert(encoder_1.get_shape()[-1] == 128)

      encoder_2 = lrelu(self.g_bn2(conv2d(encoder_1, self.gf_dim * 16, name='g_encoder_h2_conv')))
      assert(encoder_2.get_shape()[-1] == 256)

      # Middle Portion
      encoder_3 = lrelu(self.g_bn3(conv2d(encoder_2, self.gf_dim * 32, name='g_encoder_h3_conv',padding = 'SAME')))
      assert(encoder_3.get_shape()[-1] == 512)

      print(encoder_3)
      # Decoder-Architecture
      decoder_3 = lrelu(self.g_bn4(deconv2d( encoder_3, output_shape = encoder_2.get_shape(), name = 'g_decoder_h3_deconv',padding='SAME')))
      assert(decoder_3.get_shape()[-1] == 256)
      print(decoder_3)

      decoder_2 = lrelu(self.g_bn5(deconv2d( decoder_3, output_shape = encoder_1.get_shape(), name = 'g_decoder_h2_deconv')))
      assert(decoder_2.get_shape()[-1] == 128)
      print(decoder_2)

      decoder_1 = lrelu(self.g_bn6(deconv2d( decoder_2, output_shape = encoder_0.get_shape(), name = 'g_decoder_h1_deconv')))
      assert(decoder_1.get_shape()[-1] == 64)
      print(decoder_1)

      decoder_0 = self.g_bn7(deconv2d( decoder_1, output_shape = z.get_shape(), name = 'g_decoder_h0_deconv'))
      assert(decoder_0.get_shape()[-1] == 1)
      print(decoder_0)

      # PLLLLLLLLLLLLLLLLLLLLLEASEEEEEEEEEEEEEEEEEEEEEEEEEEEEE CHECKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
      # return tf.nn.tanh(decoder_0,name='g_output')

      return tf.nn.sigmoid(decoder_0), decoder_0

  # =========================================================================================================
  def sampler(self, z, y=None):
    with tf.variable_scope("generator") as scope:
      scope.reuse_variables()

      s_h, s_w = self.output_height, self.output_width
      s_h2, s_w2 = conv_out_size_same(s_h, 2), conv_out_size_same(s_w, 2)
      s_h4, s_w4 = conv_out_size_same(s_h2, 2), conv_out_size_same(s_w2, 2)
      s_h8, s_w8 = conv_out_size_same(s_h4, 2), conv_out_size_same(s_w4, 2)
      s_h16, s_w16 = conv_out_size_same(s_h8, 2), conv_out_size_same(s_w8, 2)

      hae0 = lrelu(self.g_bn4(conv2d(z, self.df_dim * 2, name='g_encoder_h0_conv')))
      hae1 = lrelu(self.g_bn5(conv2d(hae0, self.df_dim * 4, name='g_encoder_h1_conv')))
      hae2 = lrelu(self.g_bn6(conv2d(hae1, self.df_dim * 8, name='g_encoder_h2_conv')))

      h2, self.h2_w, self.h2_b = deconv2d(
        hae2, [self.batch_size, s_h4, s_w4, self.gf_dim * 2], name='g_decoder_h1', with_w=True)
      h2 = tf.nn.relu(self.g_bn2(h2))

      h3, self.h3_w, self.h3_b = deconv2d(
        h2, [self.batch_size, s_h2, s_w2, self.gf_dim * 1], name='g_decoder_h0', with_w=True)
      h3 = tf.nn.relu(self.g_bn3(h3))

      h4, self.h4_w, self.h4_b = deconv2d(
        h3, [self.batch_size, s_h, s_w, self.c_dim], name='g_decoder_h00', with_w=True)

      return tf.nn.tanh(h4,name='g_output')

  # =========================================================================================================
  @property
  def model_dir(self):
    return "{}_{}_{}_{}".format(
        self.dataset_name, self.batch_size,
        self.output_height, self.output_width)

  # =========================================================================================================
  def save(self, checkpoint_dir, step):
    model_name = "ALOCC_Model.model"
    checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)

    if not os.path.exists(checkpoint_dir):
      os.makedirs(checkpoint_dir)

    self.saver.save(self.sess,
            os.path.join(checkpoint_dir, model_name),
            global_step=step)

  # =========================================================================================================
  def load(self, checkpoint_dir):
    import re
    print(" [*] Reading checkpoints...")
    checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)

    ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
    if ckpt and ckpt.model_checkpoint_path:
      ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
      self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
      counter = int(next(re.finditer("(\d+)(?!.*\d)",ckpt_name)).group(0))
      print(" [*] Success to read {}".format(ckpt_name))
      return True, counter
    else:
      print(" [*] Failed to find a checkpoint")
      return False, 0

  # =========================================================================================================

  def f_check_checkpoint(self):
      self.saver = tf.train.Saver()
      self.saver.restore(self.sess, "./checkpoint_3/UCSD_128_45_45/ALOCC_Model.model-34")

    # try:
    #   tf.global_variables_initializer().run()
    # except:
    #   tf.initialize_all_variables().run()
    # print(" [*] Reading checkpoints...")
    # self.saver = tf.train.Saver()
    #
    # ckpt = tf.train.get_checkpoint_state(self.checkpoint_dir)
    # if ckpt and ckpt.model_checkpoint_path:
    #   ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
    #   self.saver.restore(self.sess, os.path.join(self.checkpoint_dir, ckpt_name))
    #   counter = int(next(re.finditer("(\d+)(?!.*\d)",ckpt_name)).group(0))
    #   print(" [*] Success to read {}".format(ckpt_name))
    #   could_load = True
    #   checkpoint_counter = counter
    # else:
    #   print(" [*] Failed to find a checkpoint")
    #   could_load = False
    #   checkpoint_counter =0
    #
    # if could_load:
    #   counter = checkpoint_counter
    #   print(" [*] Load SUCCESS")
    #   return counter
    # else:
    #   print(" [!] Load failed...")
    #   return -1

  # =========================================================================================================
  def f_test_frozen_model(self,lst_image_slices=[]):
    lst_generated_img= []
    lst_discriminator_v = []
    tmp_shape = lst_image_slices.shape

    if self.dataset_name=='UCSD':
      tmp_lst_slices = lst_image_slices.reshape(-1, tmp_shape[2], tmp_shape[3], 1)
    else:
      tmp_lst_slices = lst_image_slices
    batch_idxs = len(tmp_lst_slices) // self.batch_size
    print('start new process ...')
    for i in xrange(0, batch_idxs):
        batch_data = tmp_lst_slices[i * self.batch_size:(i + 1) * self.batch_size]

        results_g = self.sess.run(self.G, feed_dict={self.z: batch_data})
        results_d = self.sess.run(self.D, feed_dict={self.inputs: batch_data})
        #results = self.sess.run(self.sampler, feed_dict={self.z: batch_data})
        # to log some images with d values
        #for idx,image in enumerate(results_g):
        #  scipy.misc.imsave('samples/{}_{}.jpg'.format(idx,results_d[idx][0]),batch_data[idx,:,:,0])

        lst_discriminator_v.extend(results_d)
        lst_generated_img.extend(results_g)
        print('finish pp ... {}/{}'.format(i,batch_idxs))
    #f = plt.figure()
    #plt.plot(np.array(lst_discriminator_v))
    #f.savefig('samples/d_values.jpg')
    scipy.misc.imsave('./'+self.sample_dir+'/ALOCC_generated.jpg', montage(np.array(lst_generated_img)[:,:,:,0]))
    scipy.misc.imsave('./'+self.sample_dir+'/ALOCC_input.jpg', montage(np.array(tmp_lst_slices)[:,:,:,0]))
    return lst_discriminator_v
