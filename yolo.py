import colorsys
import os
import time

import numpy as np
import tensorflow as tf
from PIL import ImageDraw, ImageFont
from tensorflow.keras.layers import Input, Lambda
from tensorflow.keras.models import Model
from tensorflow.keras import backend as K

from nets.yolo import yolo_body
from utils.utils import (cvtColor, get_anchors, get_classes, preprocess_input,
                         resize_image, show_config)
from utils.utils_bbox import DecodeBox


class YOLO(object):
    _defaults = {
        #--------------------------------------------------------------------------#
        #   使用自己训练好的模型进行预测一定要修改model_path和classes_path！
        #   model_path指向logs文件夹下的权值文件，classes_path指向model_data下的txt
        #
        #   训练好后logs文件夹下存在多个权值文件，选择验证集损失较低的即可。
        #   验证集损失较低不代表mAP较高，仅代表该权值在验证集上泛化性能较好。
        #   如果出现shape不匹配，同时要注意训练时的model_path和classes_path参数的修改
        #--------------------------------------------------------------------------#
        # "model_path"        : './logs\ep020-loss0.878-val_loss0.861.h5',
        "model_paths"       : ['./log_ensemble/best_epoch_weights_1.h5','./log_ensemble/best_epoch_weights_3.h5','./log_ensemble/best_epoch_weights_5.h5'],
        "model_weights"     : [1,2,1],
        "classes_path"      : './model_data/bdd_classes.txt',
        "yolo_models"       : [],
        #---------------------------------------------------------------------#
        #   anchors_path代表先验框对应的txt文件，一般不修改。
        #   anchors_mask用于帮助代码找到对应的先验框，一般不修改。
        #---------------------------------------------------------------------#
        "anchors_path"      : './model_data/yolo_anchors.txt',
        "anchors_mask"      : [[6, 7, 8], [3, 4, 5], [0, 1, 2]],
        #---------------------------------------------------------------------#
        #   输入图片的大小，必须为32的倍数。
        #---------------------------------------------------------------------#
        "input_shape"       : [640, 640],
        #---------------------------------------------------------------------#
        #   所使用的YoloV5的版本。s、m、l、x
        #---------------------------------------------------------------------#
        "phi"               : 's',
        #---------------------------------------------------------------------#
        #   只有得分大于置信度的预测框会被保留下来
        #---------------------------------------------------------------------#
        "confidence"        : 0.3,
        #---------------------------------------------------------------------#
        #   非极大抑制所用到的nms_iou大小
        #---------------------------------------------------------------------#
        "nms_iou"           : 0.5,
        #---------------------------------------------------------------------#
        #   最大框的数量
        #---------------------------------------------------------------------#
        "max_boxes"         : 100,
        #---------------------------------------------------------------------#
        #   该变量用于控制是否使用letterbox_image对输入图像进行不失真的resize，
        #   在多次测试后，发现关闭letterbox_image直接resize的效果更好
        #---------------------------------------------------------------------#
        "letterbox_image"   : True,
    }

    @classmethod
    def get_defaults(cls, n):
        if n in cls._defaults:
            return cls._defaults[n]
        else:
            return "Unrecognized attribute name '" + n + "'"

    #---------------------------------------------------#
    #   初始化yolo
    #---------------------------------------------------#
    def __init__(self, **kwargs):
        self.__dict__.update(self._defaults)
        for name, value in kwargs.items():
            setattr(self, name, value)
            self._defaults[name] = value 
            
        #---------------------------------------------------#
        #   获得种类和先验框的数量
        #---------------------------------------------------#
        self.class_names, self.num_classes = get_classes(self.classes_path)
        self.anchors, self.num_anchors     = get_anchors(self.anchors_path)

        #---------------------------------------------------#
        #   画框设置不同的颜色
        #---------------------------------------------------#
        hsv_tuples  = [(x / self.num_classes, 1., 1.) for x in range(self.num_classes)]
        self.colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
        self.colors = list(map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)), self.colors))

        self.generate()
        
        show_config(**self._defaults)

    #---------------------------------------------------#
    #   载入模型
    #---------------------------------------------------#
    def generate(self):
        for model_path in self.model_paths:
            model_path_expend = os.path.expanduser(model_path)
            assert model_path_expend.endswith('.h5'), 'Keras model or weights must be a .h5 file.'
            
            self.model = yolo_body([None, None, 3], self.anchors_mask, self.num_classes, self.phi)
            self.model.load_weights(model_path)
            print('{} model, anchors, and classes loaded.'.format(model_path_expend))
            #---------------------------------------------------------#
            #   在DecodeBox函数中，我们会对预测结果进行后处理
            #   后处理的内容包括，解码、非极大抑制、门限筛选等
            #---------------------------------------------------------#
            self.input_image_shape = Input([2,],batch_size=1)
            inputs  = [*self.model.output, self.input_image_shape]
            outputs = Lambda(
                DecodeBox, 
                output_shape = (1,), 
                name = 'yolo_eval',
                arguments = {
                    'anchors'           : self.anchors, 
                    'num_classes'       : self.num_classes, 
                    'input_shape'       : self.input_shape, 
                    'anchor_mask'       : self.anchors_mask,
                    'confidence'        : self.confidence, 
                    'nms_iou'           : self.nms_iou, 
                    'max_boxes'         : self.max_boxes, 
                    'letterbox_image'   : self.letterbox_image
                }
            )(inputs)
            self.yolo_models.append(Model([self.model.input, self.input_image_shape], outputs))

    @tf.function
    def get_pred(self, image_data, input_image_shape):
        outs = []
        for yolo_model in self.yolo_models:
            out_boxes, out_scores, out_classes = yolo_model([image_data, input_image_shape], training=False)
            outs.append([out_boxes,out_scores,out_classes])
        return outs
    #---------------------------------------------------#
    #   检测图片
    #---------------------------------------------------#
    def detect_image(self, image,image_name = "sudo.jpg",crop = False, count = False):
        #---------------------------------------------------------#
        #   在这里将图像转换成RGB图像，防止灰度图在预测时报错。
        #   代码仅仅支持RGB图像的预测，所有其它类型的图像都会转化成RGB
        #---------------------------------------------------------#
        image       = cvtColor(image)
        #---------------------------------------------------------#
        #   给图像增加灰条，实现不失真的resize
        #   也可以直接resize进行识别
        #---------------------------------------------------------#
        image_data  = resize_image(image, (self.input_shape[1], self.input_shape[0]), self.letterbox_image)
        #---------------------------------------------------------#
        #   添加上batch_size维度，并进行归一化
        #---------------------------------------------------------#
        image_data  = np.expand_dims(preprocess_input(np.array(image_data, dtype='float32')), 0)

        #---------------------------------------------------------#
        #   将图像输入网络当中进行预测！
        #---------------------------------------------------------#
        input_image_shape = np.expand_dims(np.array([image.size[1], image.size[0]], dtype='float32'), 0)
        out_boxes, out_scores, out_classes = self.ensemble_predict(image_data,input_image_shape)

        print('Found {} boxes for {}'.format(len(out_boxes), 'img'))
        #---------------------------------------------------------#
        #   设置字体与边框厚度
        #---------------------------------------------------------#
        font        = ImageFont.truetype(font='./model_data/simhei.ttf', size=np.floor(3e-2 * image.size[1] + 0.5).astype('int32'))
        thickness   = int(max((image.size[0] + image.size[1]) // np.mean(self.input_shape), 1))
        #---------------------------------------------------------#
        #   计数
        #---------------------------------------------------------#
        if count:
            print("top_label:", out_classes)
            classes_nums    = np.zeros([self.num_classes])
            for i in range(self.num_classes):
                num = np.sum(out_classes == i)
                if num > 0:
                    print(self.class_names[i], " : ", num)
                classes_nums[i] = num
            print("classes_nums:", classes_nums)
        #---------------------------------------------------------#
        #   是否进行目标的裁剪
        #---------------------------------------------------------#
        if crop:
            for i, c in list(enumerate(out_boxes)):
                top, left, bottom, right = out_boxes[i]
                top     = max(0, np.floor(top).astype('int32'))
                left    = max(0, np.floor(left).astype('int32'))
                bottom  = min(image.size[1], np.floor(bottom).astype('int32'))
                right   = min(image.size[0], np.floor(right).astype('int32'))
                
                dir_save_path = "img_crop"
                if not os.path.exists(dir_save_path):
                    os.makedirs(dir_save_path)
                crop_image = image.crop([left, top, right, bottom])
                crop_image.save(os.path.join(dir_save_path, "crop_" + str(i) + ".png"), quality=95, subsampling=0)
                print("save crop_" + str(i) + ".png to " + dir_save_path)

        
        #---------------------------------------------------------#
        #   图像绘制
        #---------------------------------------------------------#
        for i, c in list(enumerate(out_classes)):
            predicted_class = self.class_names[int(c)]
            box             = out_boxes[i]
            score           = out_scores[i]

            top, left, bottom, right = box

            top     = max(0, np.floor(top).astype('int32'))
            left    = max(0, np.floor(left).astype('int32'))
            bottom  = min(image.size[1], np.floor(bottom).astype('int32'))
            right   = min(image.size[0], np.floor(right).astype('int32'))

            label = '{} {:.2f}'.format(predicted_class, score)
            draw = ImageDraw.Draw(image)
            label_size = draw.textsize(label, font)
            label = label.encode('utf-8')
            
            if top - label_size[1] >= 0:
                text_origin = np.array([left, top - label_size[1]])
            else:
                text_origin = np.array([left, top + 1])

            for i in range(thickness):
                draw.rectangle([left + i, top + i, right - i, bottom - i], outline=self.colors[c])
            draw.rectangle([tuple(text_origin), tuple(text_origin + label_size)], fill=self.colors[c])
            draw.text(text_origin, str(label,'UTF-8'), fill=(0, 0, 0), font=font)
            del draw

        return image

    def get_FPS(self, image, test_interval):
        #---------------------------------------------------------#
        #   在这里将图像转换成RGB图像，防止灰度图在预测时报错。
        #   代码仅仅支持RGB图像的预测，所有其它类型的图像都会转化成RGB
        #---------------------------------------------------------#
        image       = cvtColor(image)
        #---------------------------------------------------------#
        #   给图像增加灰条，实现不失真的resize
        #   也可以直接resize进行识别
        #---------------------------------------------------------#
        image_data  = resize_image(image, (self.input_shape[1], self.input_shape[0]), self.letterbox_image)
        #---------------------------------------------------------#
        #   添加上batch_size维度，并进行归一化
        #---------------------------------------------------------#
        image_data  = np.expand_dims(preprocess_input(np.array(image_data, dtype='float32')), 0)
        
        #---------------------------------------------------------#
        #   将图像输入网络当中进行预测！
        #---------------------------------------------------------#
        input_image_shape = np.expand_dims(np.array([image.size[1], image.size[0]], dtype='float32'), 0)
        out_boxes, out_scores, out_classes = self.get_pred(image_data, input_image_shape) 

        t1 = time.time()
        for _ in range(test_interval):
            out_boxes, out_scores, out_classes = self.get_pred(image_data, input_image_shape) 
        t2 = time.time()
        tact_time = (t2 - t1) / test_interval
        return tact_time

    def detect_heatmap(self, image, heatmap_save_path):
        import cv2
        import matplotlib.pyplot as plt
        def sigmoid(x):
            y = 1.0 / (1.0 + np.exp(-x))
            return y
        #---------------------------------------------------------#
        #   在这里将图像转换成RGB图像，防止灰度图在预测时报错。
        #   代码仅仅支持RGB图像的预测，所有其它类型的图像都会转化成RGB
        #---------------------------------------------------------#
        image       = cvtColor(image)
        #---------------------------------------------------------#
        #   给图像增加灰条，实现不失真的resize
        #   也可以直接resize进行识别
        #---------------------------------------------------------#
        image_data  = resize_image(image, (self.input_shape[1], self.input_shape[0]), self.letterbox_image)
        #---------------------------------------------------------#
        #   添加上batch_size维度，并进行归一化
        #---------------------------------------------------------#
        image_data  = np.expand_dims(preprocess_input(np.array(image_data, dtype='float32')), 0)
        
        output  = self.model.predict(image_data)
        
        plt.imshow(image, alpha=1)
        plt.axis('off')
        mask    = np.zeros((image.size[1], image.size[0]))
        for sub_output in output:
            b, h, w, c = np.shape(sub_output)
            sub_output = np.reshape(sub_output, [b, h, w, 3, -1])[0]
            score      = np.max(sigmoid(sub_output[..., 4]), -1)
            score      = cv2.resize(score, (image.size[0], image.size[1]))
            normed_score    = (score * 255).astype('uint8')
            mask            = np.maximum(mask, normed_score)
            
        plt.imshow(mask, alpha=0.5, interpolation='nearest', cmap="jet")

        plt.axis('off')
        plt.subplots_adjust(top=1, bottom=0, right=1,  left=0, hspace=0, wspace=0)
        plt.margins(0, 0)
        plt.savefig(heatmap_save_path, dpi=200, bbox_inches='tight', pad_inches = -0.1)
        print("Save to the " + heatmap_save_path)
        plt.show()
        
    #---------------------------------------------------#
    #   检测图片
    #---------------------------------------------------#
    def get_map_txt(self, image_id, image, class_names, map_out_path):
        f = open(os.path.join(map_out_path, "detection-results/"+image_id+".txt"),"w") 
        #---------------------------------------------------------#
        #   在这里将图像转换成RGB图像，防止灰度图在预测时报错。
        #---------------------------------------------------------#
        image       = cvtColor(image)
        #---------------------------------------------------------#
        #   给图像增加灰条，实现不失真的resize
        #   也可以直接resize进行识别
        #---------------------------------------------------------#
        image_data  = resize_image(image, (self.input_shape[1], self.input_shape[0]), self.letterbox_image)
        #---------------------------------------------------------#
        #   添加上batch_size维度，并进行归一化
        #---------------------------------------------------------#
        image_data  = np.expand_dims(preprocess_input(np.array(image_data, dtype='float32')), 0)

        #---------------------------------------------------------#
        #   将图像输入网络当中进行预测！
        #---------------------------------------------------------#
        input_image_shape = np.expand_dims(np.array([image.size[1], image.size[0]], dtype='float32'), 0)
        out_boxes, out_scores, out_classes = self.ensemble_predict(image_data, input_image_shape) 

        for i, c in enumerate(out_classes):
            predicted_class             = self.class_names[int(c)]
            try:
                score                   = str(out_scores[i].numpy())
            except:
                score                   = str(out_scores[i])
            top, left, bottom, right    = out_boxes[i]
            if predicted_class not in class_names:
                continue

            f.write("%s %s %s %s %s %s\n" % (predicted_class, score[:6], str(int(left)), str(int(top)), str(int(right)),str(int(bottom))))

        f.close()
        return 
    
    def iou(self,box1, box2):
        '''
        两个框（二维）的 iou 计算

        注意：边框以左上为原点

        box:[top, left, bottom, right]
        '''
        in_h = min(box1[2], box2[2]) - max(box1[0], box2[0])
        in_w = min(box1[3], box2[3]) - max(box1[1], box2[1])
        inter = 0 if in_h<0 or in_w<0 else in_h*in_w
        union = (box1[2] - box1[0]) * (box1[3] - box1[1]) + \
                (box2[2] - box2[0]) * (box2[3] - box2[1]) - inter
        iou = inter / union
        return iou

    def ensemble_predict(self,image_data,input_image_shape):
        outs = self.get_pred(image_data, input_image_shape)
        out_boxes_sum = outs[0][0]
        out_scores_sum = outs[0][1]
        out_classes_sum = outs[0][2]
        out_weights_sum = tf.ones(out_scores_sum.shape.as_list()[0])*self.model_weights[0]
        if len(outs) > 1:
            for i in range(1,len(outs)):
                out_boxes = outs[i][0]
                out_scores = outs[i][1]
                out_classes = outs[i][2]
                out_weights = tf.ones(out_scores.shape.as_list()[0])*self.model_weights[i]
                
                out_boxes_sum = tf.concat([out_boxes_sum,out_boxes],0)
                out_scores_sum = tf.concat([out_scores_sum,out_scores],0)
                out_classes_sum = tf.concat([out_classes_sum,out_classes],0)
                out_weights_sum = tf.concat([out_weights_sum,out_weights],0)

            nms_index = self.nms(out_boxes_sum,out_scores_sum,out_classes_sum,out_weights_sum)

            out_boxes_sum = K.gather(out_boxes_sum, nms_index)
            out_scores_sum = K.gather(out_scores_sum, nms_index)
            out_classes_sum = K.gather(out_classes_sum,nms_index)

        return out_boxes_sum, out_scores_sum,out_classes_sum

    def nms(self,boxes,scores,classes,weights,iou_threshold=0.35):
        picked = []
        sort_index = np.argsort(scores)
        while sort_index.size > 0:
            current = sort_index[-1]
            sort_index = np.delete(sort_index,-1)
            current_box = boxes[current]
            current_class = classes[current]

            temp = []
            count = weights[current]

            for i in (sort_index):
                if (current_class == classes[i]) and self.iou(current_box,boxes[i]) > iou_threshold:
                    count += weights[i]
                else:
                    temp.append(i)
            if count >= len(self.model_weights)//2+1:
                picked.append(current)
            sort_index = np.array(temp)
        return tf.convert_to_tensor(picked, dtype=tf.int32)
            